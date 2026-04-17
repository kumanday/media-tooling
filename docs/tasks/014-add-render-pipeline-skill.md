---
title: Add media-render-pipeline skill
milestone: M3
priority: 3
estimate: 2
blockedBy: [009, 010, 012]
blocks: []
parent: null
---

## Summary

Create a new `.agents/skills/media-render-pipeline/SKILL.md` that covers the full render → verify → iterate workflow, giving agents a single entry-point skill for end-to-end video production.

## Scope

### In scope

- New skill `.agents/skills/media-render-pipeline/SKILL.md`
- End-to-end workflow: transcribe → pack → reason → EDL → render → verify → iterate
- Strategy confirmation before execution (Hard Rule 11)
- Self-evaluation loop (max 3 passes)
- Session memory integration
- All outputs in project directory (Hard Rule 12)
- Anti-patterns and hard rules as guardrails within the skill

### Out of scope

- Changes to existing skills
- Code changes to Python modules
- Manim or animation-specific guidance (task 018)

## Deliverables

- `.agents/skills/media-render-pipeline/SKILL.md`

## Acceptance Criteria

- [ ] SKILL.md covers full pipeline: transcribe → pack → reason → EDL → render → verify → iterate
- [ ] Includes 8-step process (inventory → pre-scan → converse → propose strategy → execute → preview → self-eval → iterate+persist)
- [ ] Strategy confirmation step before execution (Hard Rule 11)
- [ ] Self-eval loop with max 3 passes documented
- [ ] Session memory protocol referenced
- [ ] All 12 hard rules and 13 anti-patterns included or referenced
- [ ] YAML frontmatter with name and description for agent routing

## Test Plan

- Manual review of SKILL.md content
- `scripts/check.sh` passes (no source changes)

## Context

- This skill synthesizes guidance from video-use's top-level SKILL.md
- Reference: `/Users/magos/dev/trilogy/writing/video-use/SKILL.md`
- Depends on: tasks 009 (EDL renderer), 010 (verify), 012 (hard rules)
- Integration plan: `docs/video-use-integration-plan.md` — Skill updates section (new render-pipeline skill)

## Definition of Ready

- [ ] Depends on tasks 009, 010, 012 being complete
- [x] video-use SKILL.md available as reference
- [x] A coding agent could begin execution once dependencies are complete
