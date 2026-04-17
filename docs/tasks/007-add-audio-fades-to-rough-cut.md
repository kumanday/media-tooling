---
title: Add 30ms audio fades to rough-cut assembly
milestone: M2
priority: 2
estimate: 2
blockedBy: []
blocks: [009]
parent: null
---

## Summary

Add 30ms audio fade-in and fade-out at every segment boundary in `rough_cut.py` to prevent audio pops/clicks at cut points.

## Scope

### In scope

- Modify `src/media_tooling/rough_cut.py` to add 30ms `afade` in/out at every segment boundary
- Apply during segment extraction, before concat
- Update existing tests that verify segment output

### Out of scope

- Loudness normalization (task 008)
- EDL renderer changes (task 009)
- Changes to card/image segment rendering (only clip segments need fades)

## Deliverables

- Modified `src/media_tooling/rough_cut.py`
- Updated tests in `tests/` (if existing rough_cut tests)

## Acceptance Criteria

- [ ] Every clip segment in rough cut has 30ms afade in at start and 30ms afade out at end
- [ ] Card and image segments (which have silent audio) are unaffected
- [ ] Fades are applied during segment extraction, before concat demuxer
- [ ] No audible pop/click at any segment boundary in assembled output
- [ ] Existing rough_cut tests still pass
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Current rough cut: `src/media_tooling/rough_cut.py` — extracts segments then concats via ffmpeg concat demuxer
- Hard Rule 3: 30ms audio fades at every segment boundary
- ffmpeg `afade` filter: `afade=t=in:st=0:d=0.03,afade=t=out:st=<duration-0.03>:d=0.03`
- Integration plan: `docs/video-use-integration-plan.md` Phase 2, item 5

## Definition of Ready

- [x] rough_cut.py segment extraction code is well-understood
- [x] ffmpeg afade filter syntax is straightforward
- [x] Hard Rule 3 specifies exact fade duration (30ms)
- [x] A coding agent could begin execution without additional planning context

## Notes

30ms is short enough to be imperceptible but long enough to prevent the audio pop that occurs when a waveform is abruptly cut. This is one of the most impactful small changes for production quality.
