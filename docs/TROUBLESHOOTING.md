# Troubleshooting

Start with these, they answer most questions. `shipm init --check` always exits 0; read its last line ("Ready: yes." or what is left)
or use `--json` and look at `ready`:

```
shipm init --check     # setup state, read only
shipm init --more      # every row, with what each one needs
```

Run commands from your clone (`cd ~/Developer/shipmiracle`) if `shipm` is not found; use `./bin/shipm` instead.

## 1. The hook does not fire (the gate never says anything)

Hooks are read when a Claude Code chat starts, and only apply to projects inside your projects folder (default `~/Developer`).

```
shipm sync --dry-run            # shows what would change in ~/.claude/settings.json, writes nothing
shipm sync                      # writes the Shipmiracle hook entries (owner command, in a terminal)
grep -c shipmiracle ~/.claude/settings.json
```

Then start a new chat. If the project sits outside the projects folder, the gate ignores it by design.

## 2. "Shipmiracle gate OFF: hook script missing"

A registered hook points at a script that no longer exists (a moved or deleted clone, or a temporary folder). The hook fails open on
purpose so Claude Code keeps working, and warns you instead.

```
shipm sync --repair-hooks           # dry run: lists the stale entries
shipm sync --repair-hooks --apply   # removes only those entries
shipm sync                          # registers the current clone
```

## 3. Touch ID helper missing

The stronger owner check (macOS) needs a small helper built on your Mac. It is compiled locally, nothing is downloaded.

```
bin/shipm-presence-build --check    # 0 = built and unchanged, 1 = not built or changed, 2 = no Swift compiler
bin/shipm-presence-build            # build it (terminal only, asks for a typed yes)
```

Exit 2: install the Xcode command line tools (`xcode-select --install`). Without the helper the weaker typed confirmation is used
(see "Known residuals" in the README). The helper has not been verified on a real Mac by someone other than the author.

## 4. The panel shows nothing

```
shipm init --check          # is the VS Code panel row ready?
bin/install-shipm-ext       # (re)install the panel extension
shipm projects              # does the registry list your projects?
```

Reload the VS Code window afterwards. The panel's own notes are in `~/.local/state/shipmiracle-diag/panel-trace.log`
(it holds short technical lines).

## 5. "is for the owner in a terminal, not inside a Claude Code chat"

Setup, uninstall, sync and similar commands refuse to run inside a chat on purpose. Open a normal terminal and run them there.

## 6. Setup stops and waits, or says it was paused

The input ended at a question. Run `shipm init` again: it resumes. To run one row: `shipm init --step ROW`. To skip an optional row:
`shipm init --skip ROW`. Row names are in `shipm init --more`.

## 7. python3 is too old, or node is missing

`python3 --version` must be 3.9 or newer, `node --version` 18 or newer. The README has the install line for your system.
Shipmiracle only prints these lines; it never installs software for you.

## 8. Claude Code login is not detected

```
claude --version
claude          # sign in in the terminal, then run: shipm init --check
```

The login check depends on the `claude` command line and may need adjusting for your version; if the check is wrong but `claude` works,
open an issue with your `claude --version`.

## 9. `code: command not found`

In VS Code: Command Palette, "Shell Command: Install 'code' command in PATH" (macOS). On WSL 2 install VS Code on Windows, then use its
Remote - WSL extension; `code` must work inside Ubuntu. Then run `shipm init` again.

## 10. Git name or email missing

```
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

Shipmiracle never writes your git settings itself.

## 11. Hook in a temporary folder

A hook script that lives in a temporary folder will vanish. `shipm sync --repair-hooks` (dry run) lists such entries. Same repair as problem 2.

## 12. Uninstall skipped a file

A file you changed after setup is skipped and reported, not overwritten. Compare it with the backup under
`~/.local/state/shipmiracle/v1/install-backups/`, decide, and run the uninstall again. See [UNINSTALL.md](UNINSTALL.md).

## 13. Native Windows

`shipm` stops at once with "use WSL 2" and changes nothing. Run `wsl --install`, open Ubuntu, and follow [INSTALL.md](INSTALL.md) there.
Keep projects in the Linux home folder, not under `/mnt/c`.

## 14. Linux and WSL 2 (experimental)

Known from the project's own checklist, not hidden:

- No awake guard (macOS only) and no system pop-ups on WSL 2.
- The daily job is a systemd user timer; uninstall does not remove it yet (see [UNINSTALL.md](UNINSTALL.md)).
- At the last run of the test suites in a Linux container, 85 failures in 30 of 126 suites remained. They come from tests that assume
  macOS services and notifications, not from a broken install. Fixing them is open work.
- A real Linux desktop run and a WSL 2 run have not been done by the author.

If `bin/test-all` fails on Linux, say so in the issue with the suite names.

## 15. "Tests touched my settings"

This should never happen. Every test suite runs in a fresh temporary home, and `bin/test-all` compares a fingerprint of your real
`~/.claude/settings.json` and `~/.config/shipmiracle` before and after, and fails loudly on a change. To check it yourself:

```
shasum -a 256 ~/.claude/settings.json
bin/test-all
shasum -a 256 ~/.claude/settings.json      # must print the same line
```

On Linux use `sha256sum`. If the two lines differ, stop, keep a copy of the file, and report it as a safety issue through
[SECURITY.md](../SECURITY.md) (private route); do not post the file.

## 16. Every tool call is refused after a hooks setting went wrong

The hook program only reads `hooks.dispatcher` from `~/.config/shipmiracle/config.json`. If that file cannot be read, or the value is not one of the known words,
a public install (which has no older hook scripts) uses the current dispatcher on its own, so ordinary calls keep working and real dangers are still refused. Fix or delete the broken line in that file.
