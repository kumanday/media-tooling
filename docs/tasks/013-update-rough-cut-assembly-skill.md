---
title: Update rough-cut-assembly skill for EDL + grading + fades + loudnorm + self-eval
milestone: M3
priority: 2
estimate: 2
blockedBy: [009, 010, 012]
blocks: []
parent: null
---

## Summary

Update the `media-rough-cut-assembly` skill to cover EDL-based rendering, color grading, audio fades, loudness normalization, and self-evaluation, reflecting the full production pipeline now available.

## Scope

### In scope

- Update `.agents/skills/media-rough-cut-assembly/SKILL.md` with:
  - EDL JSON format and `media-edl-render` command
  - `media-grade` command and presets
  - Audio fades (30ms, automatic in EDL renderer)
  - `media-loudnorm` command
  - `media-verify` command for self-evaluation
  - Updated workflow: storyboard → EDL spec → render → verify → iterate
  - Reference to hard rules and anti-patterns

### Out of scope

- Creating a new skill (task 014)
- Code changes to Python modules

## Deliverables

- Updated `.agents/skills/media-rough-cut-assembly/SKILL.md`

## Acceptance Criteria

- [ ] SKILL.md documents EDL-based rendering workflow as the primary path
- [ ] SKILL.md documents `media-edl-render` with EDL JSON format and examples
- [ ] SKILL.md documents `media-grade` with auto-grade and preset options
- [ ] SKILL.md documents `media-loudnorm` for final output normalization
- [ ] SKILL.md documents `media-verify` for self-evaluation at cut boundaries
- [ ] Card/image/clip rough cut workflow documented as simpler alternative
- [ ] Hard rules and anti-patterns referenced from SKILL.md
- [ ] No changes to Python source code

## Test Plan

- Manual review of SKILL.md content
- `scripts/check.sh` passes (no source changes)

## Context

- Current skill: `.agents/skills/media-rough-cut-assembly/SKILL.md`
- Depends on: tasks 009 (EDL renderer), 010 (verify), 012 (hard rules codified)
- Integration plan: `docs/video-use-integration-plan.md` — Skill updates section

## Definition of Ready

- [ ] Depends on tasks 009, 010, 012 being complete
- [x] Current SKILL.md can be read directly
- [x] A coding agent could begin execution once dependencies are complete
