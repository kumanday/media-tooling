---
title: Add overlay compositing to EDL renderer
milestone: M4
priority: 3
estimate: 5
blockedBy: [009]
blocks: [018]
parent: null
---

## Summary

Add overlay support to the EDL renderer with PTS-shifted video overlays, enable-between time windows, and PIL-based overlay card generation.

## Scope

### In scope

- Modify `src/media_tooling/edl_render.py` to support overlays in EDL JSON
- Overlay spec: source path, start time, end time, position, z-order
- PTS-shifted (`setpts=PTS-STARTPTS+T/TB`) so overlay frame 0 lands at overlay window start — Hard Rule 4
- Enable-between time windows via `enable='between(t,start,end)'`
- PIL-based overlay card generation (simple text/counter cards using existing Pillow dep)
- Overlay composited via ffmpeg overlay filter
- Duration rules: 3-14s sync-to-narration, 0.5-2s beat-synced accents, hold final frame ≥1s, over voiceover ≥narration_length+1s
- Easing: always cubic (never linear) for animation-generated overlays
- Unit tests for overlay compositing

### Out of scope

- Manim integration (task 018)
- Remotion integration
- Parallel sub-agent spawning (agent orchestration, not code)

## Deliverables

- Modified `src/media_tooling/edl_render.py`
- Updated tests

## Acceptance Criteria

- [ ] EDL JSON supports `overlays` array with source, start, end, position, z-order
- [ ] Overlay frame 0 lands at overlay window start via PTS shift — Hard Rule 4
- [ ] `enable='between(t,start,end)'` restricts overlay visibility to time window
- [ ] PIL-based overlay cards generate correctly (text, counters)
- [ ] Overlays composited via ffmpeg overlay filter
- [ ] Subtitles still applied last (after overlays) — Hard Rule 1
- [ ] Unit tests cover: overlay spec parsing, PTS shift, enable-between, PIL card generation
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Depends on: task 009 (EDL renderer)
- Reference: `/Users/magos/dev/trilogy/writing/video-use/helpers/render.py` — `build_final_composite`
- Hard Rule 4: PTS shift so overlay frame 0 lands at overlay window start
- Hard Rule 1: Subtitles applied last (after overlays)
- Integration plan: `docs/video-use-integration-plan.md` Phase 4, item 10

## Definition of Ready

- [ ] Depends on task 009 being complete
- [x] Overlay compositing pattern from video-use render.py
- [x] Hard Rules 1 and 4 clearly specified
- [x] A coding agent could begin execution once dependency is complete

## Notes

Start with PIL-based overlays (we already have Pillow as a dependency). Manim and Remotion are more complex and can be added as optional enhancements later. The key production rule is PTS shift — without it, overlays will drift out of sync with the video timeline.
