---
title: Add EDL-based word-boundary editing renderer
milestone: M3
priority: 1
estimate: 8
blockedBy: [004, 006, 007, 008]
blocks: [010, 013, 017]
parent: null
---

## Summary

Add a `media-edl-render` command that accepts an EDL (Edit Decision List) JSON spec with word-aligned cut points, per-segment grade/fade/subtitle directives, and produces a final assembled video with all production corrections applied per-segment.

## Scope

### In scope

- New module `src/media_tooling/edl_render.py` with core logic
- EDL JSON format: version, sources, ranges (source/start/end/beat/quote/reason/grade), overlays, subtitles, total_duration_s
- Per-segment extraction with word-boundary-aligned cuts
- Padding: 30-200ms working window at cut edges (absorbs 50-100ms timestamp drift)
- Per-segment color grading integration (from grade.py)
- 30ms audio fades at every segment boundary
- Lossless concat via ffmpeg concat demuxer
- Master SRT with output-timeline offsets (`output_time = word.start - segment_start + segment_offset`) — Hard Rule 5
- Subtitle burning applied last — Hard Rule 1
- Two-pass loudness normalization on final output
- CLI entry point `media-edl-render`
- `pyproject.toml` entry point registration
- Unit tests in `tests/test_edl_render.py`

### Out of scope

- Overlay compositing (task 017)
- Self-evaluation (task 010)
- Filler word identification (agent reasoning, not code)
- Changes to existing rough_cut.py (keep card/image/clip spec as fallback)

## Deliverables

- `src/media_tooling/edl_render.py`
- `tests/test_edl_render.py`
- Updated `pyproject.toml` with `media-edl-render` entry point

## Acceptance Criteria

- [ ] `media-edl-render edl.json -o final.mp4` produces assembled video from EDL spec
- [ ] EDL JSON schema validates: version, sources, ranges with source/start/end/beat/quote/reason/grade
- [ ] Each range extracted from source with padding (30-200ms working window)
- [ ] Never cuts inside a word — Hard Rule 6
- [ ] 30ms audio fades applied at every segment boundary — Hard Rule 3
- [ ] Per-segment grade applied during extraction — Hard Rule 2
- [ ] Concat via ffmpeg concat demuxer (lossless) — Hard Rule 2
- [ ] Master SRT built with output-timeline offsets — Hard Rule 5
- [ ] Subtitles burned last in filter chain — Hard Rule 1
- [ ] Two-pass loudnorm applied on final output
- [ ] Existing rough_cut.py still works unchanged
- [ ] Unit tests cover: EDL parsing, segment extraction, padding, SRT offset calculation, concat
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Reference: `/Users/magos/dev/trilogy/writing/video-use/helpers/render.py` — full EDL render pipeline
- Depends on: burn_subtitles.py (task 004), grade.py (task 006), loudnorm.py (task 008), audio fades pattern (task 007)
- EDL JSON format specified in integration plan
- This is the central integration point — it composes grading, fades, subtitles, and loudnorm into a single production pipeline
- Keep existing rough_cut.py as a simpler alternative for card/image/clip-based assemblies
- Integration plan: `docs/video-use-integration-plan.md` Phase 3, item 6

## Definition of Ready

- [ ] Depends on tasks 004, 006, 007, 008 (all M2 render-quality primitives)
- [x] EDL JSON schema specified in integration plan
- [x] Reference implementation in video-use render.py
- [x] Hard Rules 1-6 clearly specified
- [x] A coding agent could begin execution once M2 tasks are complete

## Notes

This is the most complex task in the plan. It composes all the M2 primitives (grade, fades, subtitles, loudnorm) into a speech-aware editing pipeline. The EDL format enables agents to reason about cuts at the word level rather than the clip level.
