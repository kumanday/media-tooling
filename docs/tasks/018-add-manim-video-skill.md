---
title: Add Manim video skill
milestone: M4
priority: 4
estimate: 3
blockedBy: [017]
blocks: []
parent: null
---

## Summary

Add a `.agents/skills/manim-video/SKILL.md` sub-skill for mathematical and technical animation generation using Manim Community Edition, adapted from video-use's manim skill.

## Scope

### In scope

- New skill `.agents/skills/manim-video/SKILL.md`
- 8 animation modes: concept explainer, equation derivation, algorithm visualization, data story, architecture diagram, paper explainer, 3D visualization, custom
- Manim production workflow: PLAN → CODE → RENDER → STITCH → AUDIO → REVIEW
- Color palettes (Classic 3B1B, Warm academic, Neon tech, Monochrome)
- Creative divergence strategies (SCAMPER, Assumption Reversal)
- `manim` as optional dependency in `pyproject.toml`
- Reference docs (subset of video-use's 13 docs, prioritized for most-used content)

### Out of scope

- Full port of all 13 reference docs (curate to most essential 5-6)
- Changes to edl_render.py (overlay compositing is task 017)
- Remotion integration

## Deliverables

- `.agents/skills/manim-video/SKILL.md`
- `.agents/skills/manim-video/references/` (5-6 curated reference docs)
- Updated `pyproject.toml` with `[project.optional-dependencies] animations = ["manim>=0.20"]`

## Acceptance Criteria

- [ ] SKILL.md defines 8 animation modes with reference doc mappings
- [ ] SKILL.md includes PLAN → CODE → RENDER → STITCH → AUDIO → REVIEW workflow
- [ ] Color palettes and typography scales specified
- [ ] Easing rules documented (cubic only, never linear)
- [ ] 5-6 curated reference docs in `.agents/skills/manim-video/references/`
- [ ] `manim` listed as optional dependency in pyproject.toml
- [ ] No changes to Python source code (skill only)

## Test Plan

- Manual review of SKILL.md and references
- `scripts/check.sh` passes (no source changes)

## Context

- Reference: `/Users/magos/dev/trilogy/writing/video-use/skills/manim-video/SKILL.md`
- Reference: `/Users/magos/dev/trilogy/writing/video-use/skills/manim-video/references/` (13 docs)
- Depends on: task 017 (overlay compositing in EDL renderer) for rendering integration
- Integration plan: `docs/video-use-integration-plan.md` Phase 4, item 10

## Definition of Ready

- [ ] Depends on task 017 being complete (for rendering integration)
- [x] Full reference skill available at video-use/skills/manim-video/
- [x] A coding agent could begin execution once dependency is complete

## Notes

Curate the 13 reference docs down to the 5-6 most essential: animations.md, mobjects.md, scene-planning.md, production-quality.md, rendering.md, and equations.md. The others can be added on demand.
