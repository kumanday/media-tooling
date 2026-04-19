# AGENTS.md

This file provides persistent context for AI agents working on this repository.

## Project Overview

media-tooling: A monorepo of media production skills and tools, including video generation, animation, and compositing pipelines.

## Technology Stack

- Language: Python 3.12+
- Framework: Manim Community Edition (animations), ffmpeg (video I/O)
- Testing: None (skill-only changes)
- Build: pyproject.toml with optional dependency groups

## Skills Structure

- `.agents/skills/manim-video/` — Manim video production pipeline skill
  - `SKILL.md` — Main skill definition (8 animation modes, PLAN→CODE→RENDER→STITCH→AUDIO→REVIEW workflow)
  - `references/` — Curated reference docs (animations, equations, mobjects, production-quality, rendering, scene-planning)
- `.agents/skills/linear/` — Linear issue tracker integration
- `.agents/skills/commit/` — Git commit conventions
- `.agents/skills/push/` — Remote push workflow
- `.agents/skills/pull/` — Remote sync workflow
- `.agents/skills/land/` — PR merge workflow

## Coding Standards

### General

- Keep functions small and focused
- Write self-documenting code with clear names
- Add comments only for "why", not "what"
- Follow existing patterns in the codebase
- Use `font=MONO` for all Text/MarkupText/BulletedList/DecimalNumber examples in Manim skill docs
- Use cubic easing (smooth/rush_into/rush_from) for entry/exit/draw animations; linear only for continuous-motion (Rotating)
- Always add `self.wait()` after key animation reveals

### Formatting

- Reference docs: Markdown with Python code blocks
- PR body: Clean Evidence section with acceptance criteria verification

### Testing

No automated tests for skill-only changes (markdown documentation).

## Project Structure

```
.
├── .agents/skills/          # Agent skills (manim-video, linear, commit, push, pull, land)
├── src/media_tooling/       # Python package source
├── pyproject.toml           # Project config with optional dependency groups
├── AGENTS.md                # This file
├── WORKFLOW.md              # OpenSymphony workflow configuration
└── README.md                # Project readme
```

## Dependencies

### Runtime

- manim>=0.20 (optional, via `pip install "media-tooling[animations]"`)

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `LINEAR_API_KEY` | Linear GraphQL API key for issue tracking | Yes (for Linear ops) |

## PR Requirements

Before submitting a PR:

1. Skill content reviewed for consistency (font=MONO, easing rules, trailing newlines)
2. No Python source code changes for skill-only PRs
3. Reference docs cross-references verified (no broken links)
4. pyproject.toml optional deps updated if needed

## Architecture Decisions

### Manim Skill Font Convention

- **Context**: All Text() examples need consistent font specification
- **Decision**: Use `font=MONO` constant (set to "Menlo") for all Text, MarkupText, BulletedList, DecimalNumber examples
- **Consequences**: LaTeX-based classes (MathTex, Tex) don't need font=MONO since they use LaTeX rendering

### Easing Rules

- **Context**: Linear easing looks unnatural for entry/exit animations
- **Decision**: Cubic easing (smooth/rush_into/rush_from) for all entry/exit/draw; linear only for continuous-motion (Rotating)
- **Consequences**: All animation examples must use cubic easing unless explicitly continuous-motion

## Known Issues / Gotchas

- `LINEAR_API_KEY` must be set in environment for Linear skill operations
- PR body edits with special characters (→) can corrupt via `gh pr edit --body`; use `--body-file` instead

## Preserved Existing AGENTS.md

The following content was preserved from the repository's previous `AGENTS.md` during `opensymphony init`.

# Media Tooling Development Context

This `AGENTS.md` is only for developing `media-tooling` itself.

- Read [docs/DEVELOPMENT.md](/Users/magos/dev/trilogy/writing/media-tooling/docs/DEVELOPMENT.md) before making substantial changes.
- Keep user-facing execution guidance out of this file. Project workspaces should get their managed `AGENTS.md` block from [project_AGENTS.md](/Users/magos/dev/trilogy/writing/media-tooling/src/media_tooling/templates/project_AGENTS.md) via `media-tooling-init`.
- When execution posture changes, update the packaged `.agents/skills/`, the project `AGENTS.md` template, and the user docs together.
- Run `bash scripts/check.sh` from the repo root before committing.
