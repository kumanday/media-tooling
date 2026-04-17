---
title: Update subtitle-pipeline skill for packing + timeline view
milestone: M1
priority: 2
estimate: 1
blockedBy: [001, 002]
blocks: [013]
parent: null
---

## Summary

Update the `media-subtitle-pipeline` skill (`.agents/skills/media-subtitle-pipeline/SKILL.md`) to cover the new packed transcript and timeline view commands, guiding agents on when and how to use them.

## Scope

### In scope

- Update `.agents/skills/media-subtitle-pipeline/SKILL.md` with:
  - Packed transcript generation step (after transcription)
  - Timeline view usage guidance (when to call at decision points)
  - Updated workflow: transcribe → pack → (optional) timeline view
- Ensure packed transcript is the default output format agents consume

### Out of scope

- Changes to other skills
- Code changes to any Python modules
- Creating a new skill

## Deliverables

- Updated `.agents/skills/media-subtitle-pipeline/SKILL.md`

## Acceptance Criteria

- [ ] SKILL.md documents `media-pack-transcript` command with usage examples
- [ ] SKILL.md documents `media-timeline-view` command with usage examples
- [ ] Workflow section includes: transcribe → pack → inspect (on demand)
- [ ] Packed transcript is recommended as the primary format for agent reasoning
- [ ] Timeline view is recommended only at editing decision points, not as default output
- [ ] No changes to Python source code

## Test Plan

- Manual review of SKILL.md content
- `scripts/check.sh` passes (no source changes)

## Context

- Current skill: `.agents/skills/media-subtitle-pipeline/SKILL.md`
- New commands from tasks 001 and 002
- Integration plan: `docs/video-use-integration-plan.md` — Skill updates section

## Definition of Ready

- [x] Depends on tasks 001 and 002 being complete (commands exist)
- [x] Current SKILL.md content can be read directly
- [x] A coding agent could begin execution without additional planning context
