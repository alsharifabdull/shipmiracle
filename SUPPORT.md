# Getting help

This is a small project with one maintainer. There is no support promise and no response time.

1. Read the README, especially "Supported systems" and "Limitations".
2. Look at [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md): the most common problems come with exact commands.
3. Run `shipm init --check`: it shows the setup state and what is missing, and changes nothing. `shipm init --more` lists every row.
4. Search the existing issues.
5. Still stuck? Open an issue with the bug template. Include your system, the version (top entry of `CHANGELOG.md`), the output of
   `shipm init --check` with personal paths and names removed, and what you expected.

Do not post secrets, tokens or logs with personal paths. Security problems go to the private route in [SECURITY.md](SECURITY.md),
never to a public issue. What the tool stores on your machine: [docs/PRIVACY.md](docs/PRIVACY.md).
