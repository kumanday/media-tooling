---
type: topic-doc
area: m2-render-quality-production
visibility: public
last_memory_sync: 2026-06-14T19:02:42.455381+00:00
---

# M2 Render Quality Production

<!-- BEGIN OPENSYMPHONY MANAGED MEMORY SYNC -->

## Current model

- COE-339 contributed: PR #8: feat: add media-burn-subtitles command (merge `6534dcc`)
- COE-340 contributed: PR #11: feat(grade): add media-grade command with auto-grade, presets, and custom filter (merge `0d18336`)
- COE-341 contributed: PR #14: feat(rough-cut): add 30ms audio fades at segment boundaries (merge `03d04b5`)
- COE-342 contributed: No merged PR source was matched during capture.
- COE-346 contributed: PR #15: feat: add media-batch-burn-subtitles command (merge `9de05ac`)

## Important invariants

- Preserve the behavior described in the recent captured changes unless current code and tests show it has changed.
- Use capsule source refs to inspect the original PR or Linear issue when context is ambiguous.

## Operational flow

- No generated diagram requested for this sync.

## Known gotchas

- No area-specific gotchas were inferred from the selected memory.

## Recent changes

- COE-339: Add subtitle burning command
- COE-340: Add color grading command
- COE-341: Add 30ms audio fades to rough-cut assembly
- COE-342: Add loudness normalization command
- COE-346: Add batch subtitle burning wrapper

## Source refs

- COE-339
- COE-340
- COE-341
- COE-342
- COE-346

<!-- END OPENSYMPHONY MANAGED MEMORY SYNC -->
