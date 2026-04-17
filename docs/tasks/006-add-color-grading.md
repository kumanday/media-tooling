---
title: Add color grading command
milestone: M2
priority: 2
estimate: 3
blockedBy: []
blocks: [009]
parent: null
---

## Summary

Add a `media-grade` command with auto-grade mode, named presets, and custom ffmpeg filter passthrough, applied per-segment during extraction to avoid double-encoding.

## Scope

### In scope

- New module `src/media_tooling/grade.py` with core logic
- Auto-grade mode (default): ffmpeg `signalstats` → bounded ±8% correction
- Presets: `subtle`, `neutral_punch`, `warm_cinematic`, `none`
- Custom: `--filter '<raw ffmpeg>'` passthrough
- CLI entry point `media-grade`
- `pyproject.toml` entry point registration
- Unit tests in `tests/test_grade.py`

### Out of scope

- Integration into EDL renderer (task 009)
- Per-frame grading (per-segment only)
- GUI/LUT support

## Deliverables

- `src/media_tooling/grade.py`
- `tests/test_grade.py`
- Updated `pyproject.toml` with `media-grade` entry point

## Acceptance Criteria

- [ ] `media-grade input.mp4 -o output.mp4` applies auto-grade
- [ ] Auto-grade samples N frames via `signalstats`, computes mean brightness, RMS contrast, saturation
- [ ] Auto-grade corrections bounded to ±8% on any axis, no creative color shift
- [ ] `--preset subtle` applies subtle cleanup (contrast=1.03, sat=0.98)
- [ ] `--preset neutral_punch` applies light contrast + subtle S-curve, no hue shifts
- [ ] `--preset warm_cinematic` applies +12% contrast, crushed blacks, -12% sat, warm shadows + cool highs, filmic curve
- [ ] `--preset none` produces straight copy (no grading)
- [ ] `--filter 'eq=brightness=0.1'` applies raw ffmpeg filter string
- [ ] Applied per-segment during extraction (not post-concat) — Hard Rule 2
- [ ] Mental model follows ASC CDL (slope=highlights, offset=shadows, power=midtones, global saturation)
- [ ] Unit tests cover: auto-grade analysis, each preset, custom filter passthrough
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Reference: `/Users/magos/dev/trilogy/writing/video-use/helpers/grade.py`
- Hard Rule 2: Per-segment extract + lossless concat — grading applied during extraction, never post-concat
- ffmpeg `signalstats` filter provides per-frame statistics for auto-grade analysis
- Integration plan: `docs/video-use-integration-plan.md` Phase 2, item 4

## Definition of Ready

- [x] Reference implementation at video-use/helpers/grade.py
- [x] ffmpeg signalstats filter documentation available
- [x] Preset values specified in integration plan
- [x] A coding agent could begin execution without additional planning context

## Notes

Auto-grade's goal is "make it look clean without looking graded." The ±8% bound prevents heavy-handed correction. For creative looks, use presets or custom filters.
