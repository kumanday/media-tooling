---
title: Add subtitle burning command
milestone: M2
priority: 1
estimate: 3
blockedBy: []
blocks: [005, 009]
parent: null
---

## Summary

Add a `media-burn-subtitles` command that burns SRT subtitles into video with customizable styles, producing a final video with captions rendered directly into the image.

## Scope

### In scope

- New module `src/media_tooling/burn_subtitles.py` with core logic
- Default style (`bold-overlay`): 2-word UPPERCASE chunks, white-on-black-outline, MarginV=35
- `natural-sentence` mode: 4-7 word chunks, sentence case, break on natural pauses, larger font
- Custom style passthrough via `--style-args`
- Subtitles applied **last** in filter chain (Hard Rule 1)
- CLI entry point `media-burn-subtitles`
- `pyproject.toml` entry point registration
- Unit tests in `tests/test_burn_subtitles.py`

### Out of scope

- Batch wrapper (task 005)
- Building master SRT from EDL offsets (part of task 009)
- Integration with overlay compositing (task 017)

## Deliverables

- `src/media_tooling/burn_subtitles.py`
- `tests/test_burn_subtitles.py`
- Updated `pyproject.toml` with `media-burn-subtitles` entry point

## Acceptance Criteria

- [ ] `media-burn-subtitles input.mp4 -i subtitles.srt -o output.mp4` burns subtitles
- [ ] Default `bold-overlay` style produces 2-word UPPERCASE chunks with white-on-black-outline
- [ ] `--style natural-sentence` produces 4-7 word sentence-case chunks
- [ ] Subtitles filter is always the **last** filter in the chain (Hard Rule 1)
- [ ] Custom `--style-args` passthrough works for arbitrary ASS/SSA style overrides
- [ ] Output video retains same resolution and codec as input (H.264)
- [ ] Unit tests cover: SRT parsing, chunk grouping (2-word, natural-sentence), filter chain ordering
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Reference: `/Users/magos/dev/trilogy/writing/video-use/helpers/render.py` — `build_master_srt` and subtitles filter
- Hard Rule 1: Subtitles applied last in filter chain (otherwise overlays hide captions)
- Currently media-tooling generates `.srt` files but never burns them into video
- Uses ffmpeg `subtitles` filter with ASS style overrides for styling
- Integration plan: `docs/video-use-integration-plan.md` Phase 2, item 3

## Definition of Ready

- [x] SRT format produced by existing subtitle.py is well-understood
- [x] ffmpeg subtitles filter documentation available
- [x] Reference implementation in video-use render.py
- [x] Hard Rule 1 (subtitles last) clearly specified
- [x] A coding agent could begin execution without additional planning context

## Notes

The "subtitles last" rule is non-negotiable. If subtitles are applied before overlays, the overlays will hide the captions. This is one of the most common silent failures in video pipelines.
