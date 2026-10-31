## Stack rules — Python
- Python 3.12+ in a `.venv`; dependencies pinned in `requirements.txt` or `pyproject.toml`.
- Format and lint with `ruff`; type-check with `pyright` (the `pyright-lsp` plugin).
- Tests: `pytest -q`. Coverage for logic modules.
- Use Context7 for current library docs before using an API you are unsure of.
- Secrets in `.env` loaded by the app, never imported into tests.
