# AGENTS.md

Guidelines for AI agents working in this repository.

## Project overview

**fzf-pim** is a Textual TUI for activating Azure PIM eligible roles with multiselect.  
Authentication is fully delegated to the active `az` CLI session — no credentials are managed by the app.

## Tech stack

- Python ≥ 3.11, managed with **uv**
- [Textual](https://textual.textualize.io/) for the TUI
- Azure CLI (`az rest`) as the only Azure API transport
- Build backend: **hatchling**

## Key commands

```sh
uv run fzf-pim            # run the app
uv run fzf-pim --dry-run  # simulate activation without calling Azure APIs
uv run pytest             # run tests (if present)
```

## Project layout

```
fzf_pim/
  __main__.py          # CLI entry point (argparse → PimApp)
  app.py               # PimApp(App) root, pushes ScopeScreen on mount
  app.tcss             # Textual CSS
  azure.py             # All Azure API calls via `az rest`; dataclasses: Subscription, EligibleRole
  screens/
    scope_screen.py    # Step 1 — pick subscription scope
    roles_screen.py    # Step 2 — multiselect eligible roles
    activation_screen.py  # Step 3 — justification form + per-role progress table
```

## Conventions

- All Azure I/O lives in `azure.py`; screens are UI-only.
- Screens communicate by passing data as constructor args when pushing the next screen.
- `@work` (Textual worker) for async/background tasks inside screens.
- No external HTTP libraries — use `subprocess` + `az rest` only.
- `from __future__ import annotations` at the top of every module.

## Do / don't

- **Do** keep Azure logic in `azure.py`, not in screens.
- **Do** use `--dry-run` when testing activation flows to avoid real API calls.
- **Don't** add credentials, tokens, or secrets anywhere in the codebase.
- **Don't** introduce new dependencies without updating `pyproject.toml`.
