# Development

This file is for developers changing `media-tooling` itself.

User-facing execution context lives in project-local `AGENTS.md` files created by `media-tooling-init`, not in this repository root. Keep detailed maintenance guidance here so it does not become default execution context for user-facing runs.

## Repo posture

- run maintenance commands from the repo root
- treat this repository as the reusable toolkit engine
- keep project-specific media outputs outside this repository
- remember that `.agents/skills/` is packaged as a central asset for project-local `AGENTS.md` files to reference

## Quality gates

Use the dev dependency group and run checks from the repo root:

```bash
uv sync --group dev
bash scripts/check.sh
```

Equivalent direct commands:

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## What lives where

- `AGENTS.md`
  intentionally absent from the repo root; user execution context belongs in project workspaces
- `.agents/skills/`
  central task-routing guidance packaged into installs and referenced from project-local `AGENTS.md`
- `docs/`
  developer-oriented setup, maintenance, and reference material

## When editing the toolkit

- prefer updating shared helpers instead of duplicating batch logic
- keep user-facing execution guidance in the project-init managed block rather than the repo root
- keep implementation notes and maintenance guidance here or in other files under `docs/`
