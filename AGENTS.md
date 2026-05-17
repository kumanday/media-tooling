# AGENTS.md

This file provides persistent context for AI agents working on this repository.

## Project Overview

media-tooling: A Python CLI toolkit for media production workflows — transcription, subtitling, contact sheets, EDL-driven rendering, color grading, loudness normalization, and rough-cut assembly. Central agent skills package with project workspaces.

## Technology Stack

- Language: Python 3.12+
- Core dependencies: numpy, pillow, ffmpeg
- Transcription backends: lightning-whisper-mlx (Apple Silicon) / faster-whisper (other platforms)
- Optional animations: Manim Community Edition (via `pip install "media-tooling[animations]")
- Optional TTS: elevenlabs (via `pip install "media-tooling[elevenlabs]")
- Testing: unittest, ruff, mypy
- Build: hatchling via pyproject.toml with uv

## Skills Structure

Agent skills under `.agents/skills/`:

- `media-corpus-ingest/` — Mixed-media ingestion (subtitle + contact-sheet pipelines)
- `media-subtitle-pipeline/` — Spoken-media transcription, packing, and timeline drill-down
- `media-rough-cut-assembly/` — EDL-driven rendering, grading, loudnorm, and card/image/clip assembly
- `media-render-pipeline/` — End-to-end orchestration skill (top-level)
- `manim-video/` — Manim animation production skill (optional)
- `linear/` — Linear issue tracker integration
- `commit/` — Git commit conventions
- `push/` — Remote push workflow
- `pull/` — Remote sync workflow
- `land/` — PR merge workflow
- `convert-tasks-to-linear/` — Task-to-issue conversion helper
- `create-implementation-plan/` — Implementation planning skill
- `opensymphony-memory/` — Conversation-store persistence skill

## Coding Standards

### General

- Keep functions small and focused
- Write self-documenting code with clear names
- Add comments only for "why", not "what"
- Follow existing patterns in the codebase

### Formatting

- Reference docs: Markdown with Python code blocks

### Testing

- All Python source changes must pass `scripts/check.sh` (unittest + ruff + mypy)
- Skill-only changes (Markdown documentation) do not need new unit tests but must not break existing ones

## Project Structure

```
.
├── .agents/skills/          # Agent skills (see Skills Structure above)
├── src/media_tooling/       # Python package source and CLI entry points
├── tests/                   # Unit tests (mirrors src/ structure)
├── docs/                    # Developer and workflow documentation
├── scripts/                 # Bootstrap, check, and install scripts
├── shell/                   # Optional zsh helpers (extract, subtitle)
├── .github/                 # Pull request templates
├── pyproject.toml           # Project config with optional dependency groups
├── uv.lock                  # Locked dependency versions
├── AGENTS.md                # This file (repo-root dev context)
├── WORKFLOW.md              # OpenSymphony workflow configuration
└── README.md                # User-facing project overview
```

## Dependencies

### Runtime

- ffmpeg (system dependency)
- numpy, pillow (image processing)
- lightning-whisper-mlx or faster-whisper (transcription)
- manim>=0.20 (optional, via `pip install "media-tooling[animations]"`)
- requests (optional, via `pip install "media-tooling[elevenlabs]"`)

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `LINEAR_API_KEY` | Linear GraphQL API key for issue tracking | Yes (for Linear ops) |

## PR Requirements

Before submitting a PR:

1. Run `bash scripts/check.sh` from the repo root
2. Reference docs cross-references verified (no broken links)
3. pyproject.toml optional deps updated if needed

## Known Issues / Gotchas

- `LINEAR_API_KEY` must be set in environment for Linear skill operations
- PR body edits with special characters (→) can corrupt via `gh pr edit --body`; use `--body-file` instead

## Preserved Existing AGENTS.md

The following content was preserved from the repository's previous `AGENTS.md` during `opensymphony init`.

# Media Tooling Development Context

This `AGENTS.md` is only for developing `media-tooling` itself.

- Read [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) before making substantial changes.
- Keep user-facing execution guidance out of this file. Project workspaces should get their managed `AGENTS.md` block from [src/media_tooling/templates/project_AGENTS.md](src/media_tooling/templates/project_AGENTS.md) via `media-tooling-init`.
- When execution posture changes, update the packaged `.agents/skills/`, the project `AGENTS.md` template, and the user docs together.
- Run `bash scripts/check.sh` from the repo root before committing.
