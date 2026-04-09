# Development

This file is for developers changing `media-tooling` itself.

Normal execution context belongs in the repo root via `AGENTS.md` and the local skills. Keep detailed maintenance guidance here so it does not become default execution context for user-facing runs.

## Repo posture

- run maintenance commands from the repo root
- treat this repository as the reusable toolkit engine
- keep project-specific media outputs outside this repository

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
  persistent user-execution context for agentic runs from repo root
- `.agents/skills/`
  task-routing guidance for the main media workflows
- `docs/`
  developer-oriented setup, maintenance, and reference material

## When editing the toolkit

- prefer updating shared helpers instead of duplicating batch logic
- keep execution-facing guidance concise in `AGENTS.md`
- keep implementation notes and maintenance guidance here or in other files under `docs/`
