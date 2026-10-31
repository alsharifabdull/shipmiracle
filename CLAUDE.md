# Contributor instructions

This repository is the Shipmiracle engine: a Python 3.9 command line (`bin/shipm`), a hook dispatcher for Claude Code
(`hooks/shipm-hook`), agent definitions, project templates and a VS Code status panel.

## Rules for any change

- Read the code and the tests before you change them; the tests are the specification.
- Standard library only for Python (3.9). No new dependency without saying why in the pull request.
- Run `bin/test-all` before you say a change works, and quote the pass and fail counts.
- Run `bin/shipm release-check --tree . --no-denylist`; it must pass.
- Never put a secret, a personal name, an account name or an absolute home path in a file. Use placeholders such as
  `<your-login>` and `~/Developer`.
- Tests run with `SHIPMIRACLE_TEST=1` and a temporary HOME; never write to a real home folder, `~/.claude` or `~/.config` from a test.
- Keep changes small and focused. State what you did not verify.
