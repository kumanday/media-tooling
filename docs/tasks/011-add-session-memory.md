---
title: Add session memory convention to project template
milestone: M3
priority: 3
estimate: 1
blockedBy: []
blocks: [019]
parent: null
---

## Summary

Add a `project.md` session memory convention to the project template, enabling agents to persist strategy, decisions, reasoning, and outstanding items across sessions.

## Scope

### In scope

- Update `src/media_tooling/templates/project_AGENTS.md` to include memory protocol
- Update `src/media_tooling/project_init.py` to scaffold `edit/project.md`
- Memory format: Strategy, Decisions, Reasoning log, Outstanding items
- On startup, last session summarized in one sentence

### Out of scope

- Automatic memory management code (agent manages project.md via skill)
- Database or structured storage
- Changes to any Python modules other than project_init.py

## Deliverables

- Updated `src/media_tooling/templates/project_AGENTS.md`
- Updated `src/media_tooling/project_init.py`

## Acceptance Criteria

- [ ] `media-tooling-init` creates `edit/project.md` in new project workspaces
- [ ] project_AGENTS.md template includes memory protocol section
- [ ] Memory format specifies: Strategy, Decisions, Reasoning log, Outstanding items
- [ ] Template instructs agents to append to project.md each session
- [ ] Template instructs agents to summarize last session on startup (one sentence)
- [ ] Existing project_init.py tests still pass
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Current template: `src/media_tooling/templates/project_AGENTS.md`
- Current init: `src/media_tooling/project_init.py` — creates 11 subdirectories
- Reference: video-use SKILL.md memory section
- Integration plan: `docs/video-use-integration-plan.md` Phase 3, item 8

## Definition of Ready

- [x] Existing template and init code can be read directly
- [x] Memory format specified (Strategy, Decisions, Reasoning, Outstanding)
- [x] A coding agent could begin execution without additional planning context

## Notes

Session memory enables multi-session continuity. Without it, every new session starts from scratch. With it, the agent can pick up where it left off, recall past decisions, and track outstanding work items.
