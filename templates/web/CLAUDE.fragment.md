## Stack rules — Web (TypeScript / Node)
- TypeScript strict. Package manager: npm (lockfile committed). Node LTS as in `.nvmrc`.
- Formatting with Prettier, linting with ESLint; both run in the hook and in CI.
- Tests: `npm test` (Vitest or the project's runner); browser checks with Playwright through
  the `playwright` plugin or the built-in browser pane.
- Use Context7 for current framework docs before using an API you are unsure of.
- Accessibility: semantic HTML, keyboard navigation, labels, contrast; RTL via `dir` when the
  product language needs it.
- Secrets in `.env` only; never shipped to the client bundle.
