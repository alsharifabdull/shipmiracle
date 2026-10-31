# Security policy

## Reporting a problem

Please report vulnerabilities through GitHub private vulnerability reporting: open the repository's **Security** tab and choose
**Report a vulnerability**. Do not open a public issue for a security problem and do not post secrets, tokens or logs in any issue.

You can expect an acknowledgement within a few days. This is a small hobby-scale project: there is no bounty and no guaranteed
fix time, but reports are taken seriously.

## Scope

The tool runs locally on your Mac. It stores no passwords or API keys and makes no network calls of its own besides the tools you
already use (`git`, `gh`, `claude`, `code`). Things worth reporting: a command that writes outside the list in the README, a hook
that can be tricked into running something unexpected, a way to make it print or store a secret, or an unsafe default.

## Supported versions

Only the latest release.
