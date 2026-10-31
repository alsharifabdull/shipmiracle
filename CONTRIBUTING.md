# Contributing

This repository is a one-way export of a private working repository. Each release is one commit that replaces the whole tree.
That has two consequences:

- Pull requests cannot be merged here directly. A maintainer ports an accepted change by hand into the source repository and
  credits you in `CHANGELOG.md`; it then appears in the next release.
- Issues are welcome and are the best way to start. Use the bug or feature template.

## Before you open a pull request

Run both from the repository root:

```
bin/test-all
bin/shipm release-check --tree . --no-denylist
```

`bin/test-all` runs every suite in `tests/` (Python 3.9 and Node 18 or newer, no network). `release-check` scans the tree for
secrets, personal paths and files that must not be published. Both must pass.

## Style

Python code is standard library only and must run on 3.9. Shell scripts must pass `shellcheck`. Keep changes small and add or
update a test with every behaviour change.

## Reporting a security problem

Use the private route described in `SECURITY.md`, not an issue.
