---
title: Codify hard rules and anti-patterns into project template and code
milestone: M3
priority: 1
estimate: 2
blockedBy: []
blocks: [013, 014]
parent: null
---

## Summary

Codify the 12 production hard rules and 13 anti-patterns from video-use into the project AGENTS.md template and as code-level guardrails in relevant modules.

## Scope

### In scope

- Update `src/media_tooling/templates/project_AGENTS.md` with hard rules and anti-patterns
- Add runtime guardrails in relevant modules:
  - `burn_subtitles.py`: enforce subtitles-last filter chain order
  - `rough_cut.py`: enforce per-segment extraction + lossless concat
  - `edl_render.py` (when created): enforce padding, no-cut-inside-word
- Document hard rules in a shared location accessible to all skills
- Add anti-patterns as explicit warnings in skill definitions

### Out of scope

- Creating new skills (tasks 013, 014)
- Changing existing behavior (only adding guardrails/warnings)

## Deliverables

- Updated `src/media_tooling/templates/project_AGENTS.md`
- Guardrail checks in `burn_subtitles.py`, `rough_cut.py`
- Shared hard-rules reference in `docs/`

## Acceptance Criteria

- [ ] project_AGENTS.md template includes 12 Hard Rules section
- [ ] project_AGENTS.md template includes 13 Anti-patterns section
- [ ] burn_subtitles.py warns or errors if subtitles filter is not last in chain
- [ ] rough_cut.py validates concat demuxer usage (not single-pass filtergraph)
- [ ] A `docs/hard-rules.md` file exists listing all 12 rules and 13 anti-patterns with rationale
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Full hard rules list: `docs/video-use-integration-plan.md` — Hard Rules section
- Full anti-patterns list: `docs/video-use-integration-plan.md` — Anti-patterns section
- These rules are non-negotiable for broadcast-quality output
- Reference: video-use SKILL.md (12 Hard Rules + anti-patterns list)

## Definition of Ready

- [x] Hard rules and anti-patterns fully enumerated in integration plan
- [x] Existing code files can be read for guardrail insertion points
- [x] A coding agent could begin execution without additional planning context

## Notes

Hard rules prevent silent failures. The most dangerous bugs in video pipelines are the ones that produce visually plausible output with subtle defects — subtitles hidden behind overlays, audio pops at cuts, double-encoded segments. Codifying these rules as both documentation and runtime checks prevents regression.
