# Changelog

All notable changes are listed here. The format follows Keep a Changelog; versions follow Semantic Versioning
(0.x until a stranger has installed and removed it on a clean macOS account).

## 0.1.1

- New positioning: shipm manages all your AI projects and keeps them organized.
- New light header picture in the README.
- The website source now lives in `website/`.
- The release check accepts the website fonts.

## 0.1.0

First public export.

- The `shipm` command line and the Claude Code hook dispatcher, agent definitions, project templates, the VS Code status panel
  and the standards documents.
- `shipm init` (guided, re-runnable setup) and `shipm uninstall` (manifest-driven removal).
- `shipm release-check` (secret, identifier, file-type, closure and version checks before an export).
- Supported systems are now written down: macOS first-class, Linux and Windows through WSL 2 experimental, native Windows refused with a "use WSL 2" message.
- CI runs the full suite on Ubuntu and macOS (Python 3.9 and 3.12) and a Windows job that only checks the refusal message.
- `bin/test-linux` runs the Python suites in a local Docker container (image pinned by digest, repo mounted read-only, no network).
- Linux and WSL2: the daily job as a systemd user timer (`bin/shipm-timer`); portable shell in the project templates (`date -r`, no `sed -i ''`).
- Release note for the maintainer: the CI workflow pins every action by full commit SHA (the version tag is in a comment on the line). To update one,
  look up the new tag's commit SHA and change both.
