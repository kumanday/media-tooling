---
title: Add filmstrip + waveform visual composite (timeline view)
milestone: M1
priority: 1
estimate: 5
blockedBy: []
blocks: [003, 010]
parent: null
---

## Summary

Add a `media-timeline-view` command that produces a PNG composite of filmstrip frames + RMS audio waveform + word labels + silence gap shading + time ruler for any time range, enabling on-demand visual inspection at editing decision points.

## Scope

### In scope

- New module `src/media_tooling/timeline_view.py` with core logic
- Filmstrip: N evenly-spaced frames extracted via ffmpeg
- Waveform: RMS audio envelope rendered from audio samples
- Word labels: transcript words overlaid at timestamp positions
- Silence gap shading: regions with no speech highlighted
- Time ruler with second markers
- CLI entry point `media-timeline-view`
- Support `--start` and `--end` for time range selection
- Support `--transcript` to load JSON metadata for word labels
- `pyproject.toml` entry point registration
- Unit tests in `tests/test_timeline_view.py`

### Out of scope

- Speaker diarization coloring (future enhancement)
- Interactive/HTML output
- Integration with verify command (task 010)

## Deliverables

- `src/media_tooling/timeline_view.py`
- `tests/test_timeline_view.py`
- Updated `pyproject.toml` with `media-timeline-view` entry point and `numpy` dependency

## Acceptance Criteria

- [ ] `media-timeline-view source.mp4 -o timeline.png` produces composite PNG
- [ ] `--start 30 --end 60` limits to 30-second window
- [ ] `--transcript transcript.json` overlays word labels at correct temporal positions
- [ ] Filmstrip shows N evenly-spaced frames (default ~10)
- [ ] Waveform shows RMS audio envelope
- [ ] Silence gaps ≥400ms are shaded distinctly
- [ ] Time ruler displayed with second markers
- [ ] Default output resolution is readable (suitable for LLM vision consumption)
- [ ] Unit tests cover: frame extraction, silence detection, time range parsing, output dimensions
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Reference implementation: `/Users/magos/dev/trilogy/writing/video-use/helpers/timeline_view.py`
- This command complements `media-contact-sheet` — contact sheets are for inventory/classification; timeline_view is for editing decisions
- Uses ffmpeg for frame extraction and ffprobe for duration probing (same pattern as existing contact_sheet.py)
- JSON metadata format: see `src/media_tooling/subtitle.py` for the `words` array structure
- Dependencies: `numpy` (new), `pillow` (already have)
- Integration plan: `docs/video-use-integration-plan.md` Phase 1, item 2

## Definition of Ready

- [x] Reference implementation available at video-use/helpers/timeline_view.py
- [x] ffmpeg/ffprobe usage patterns established in existing contact_sheet.py
- [x] JSON metadata format documented in subtitle.py
- [x] numpy dependency needs addition to pyproject.toml
- [x] A coding agent could begin execution without additional planning context

## Notes

The timeline view replaces naive frame-dumping (30,000 frames × 1,500 tokens = 45M tokens of noise) with ~12KB text + a handful of targeted PNGs. It is the "visual" counterpart to the packed transcript's "text" — together they give an LLM full coverage of a video without watching it.
