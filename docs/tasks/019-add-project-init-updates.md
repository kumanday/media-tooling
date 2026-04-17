---
title: Update project-init for new commands and skill paths
milestone: M4
priority: 4
estimate: 1
blockedBy: [011, 014]
blocks: []
parent: null
---

## Summary

Update `media-tooling-init` to include new skill paths (render-pipeline, manim-video), new project directories (edit/), and ensure the project AGENTS.md template references all available commands.

## Scope

### In scope

- Update `src/media_tooling/project_init.py` to:
  - Add `edit/` directory to scaffolded structure (for session memory + EDL files)
  - Add `edit/project.md` initial file
  - Register new skills in skill path verification
- Update `src/media_tooling/templates/project_AGENTS.md` to:
  - Reference new commands: media-pack-transcript, media-timeline-view, media-burn-subtitles, media-grade, media-loudnorm, media-edl-render, media-verify
  - Reference new skills: media-render-pipeline, manim-video (optional)

### Out of scope

- Changes to skill SKILL.md files (done in their respective tasks)
- Auto-detection of optional deps (manim, ElevenLabs)

## Deliverables

- Updated `src/media_tooling/project_init.py`
- Updated `src/media_tooling/templates/project_AGENTS.md`

## Acceptance Criteria

- [ ] `media-tooling-init` creates `edit/` and `edit/project.md` in new workspaces
- [ ] Project AGENTS.md template lists all 7+ new CLI commands
- [ ] Project AGENTS.md template references render-pipeline skill
- [ ] Skill path verification includes render-pipeline SKILL.md
- [ ] Existing project_init tests still pass
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Current init: `src/media_tooling/project_init.py`
- Current template: `src/media_tooling/templates/project_AGENTS.md`
- Depends on: task 011 (session memory dirs), task 014 (render-pipeline skill)
- Integration plan: `docs/video-use-integration-plan.md` — all phases

## Definition of Ready

- [ ] Depends on tasks 011 and 014 being complete
- [x] Current project_init.py and template can be read directly
- [x] A coding agent could begin execution once dependencies are complete
