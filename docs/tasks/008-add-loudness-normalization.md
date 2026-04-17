---
title: Add loudness normalization command
milestone: M2
priority: 2
estimate: 2
blockedBy: []
blocks: [009]
parent: null
---

## Summary

Add a `media-loudnorm` command for two-pass ffmpeg loudnorm targeting -14 LUFS / -1 dBTP / LRA 11 (social media standard), with a preview mode that uses one-pass approximation for speed.

## Scope

### In scope

- New module `src/media_tooling/loudnorm.py` with core logic
- Two-pass loudnorm: first pass measures, second pass applies
- Target: -14 LUFS (integrated), -1 dBTP (true peak), LRA 11 (loudness range)
- Preview mode: single-pass approximation (faster, less precise)
- CLI entry point `media-loudnorm`
- `pyproject.toml` entry point registration
- Unit tests in `tests/test_loudnorm.py`

### Out of scope

- Integration into EDL renderer (task 009)
- Integration into rough_cut.py (can be done manually or in task 009)
- Per-channel normalization

## Deliverables

- `src/media_tooling/loudnorm.py`
- `tests/test_loudnorm.py`
- Updated `pyproject.toml` with `media-loudnorm` entry point

## Acceptance Criteria

- [ ] `media-loudnorm input.mp4 -o output.mp4` applies two-pass loudnorm
- [ ] Two-pass: first pass `loudnorm=I=-14:TP=-1:LRA=11:print_format=json`, second pass with measured values
- [ ] `--preview` flag uses single-pass approximation for speed
- [ ] Output meets -14 LUFS ±1, -1 dBTP, LRA ≤11 on verification with ffmpeg loudnorm measurement
- [ ] Unit tests cover: two-pass flow, preview mode, argument parsing
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Reference: `/Users/magos/dev/trilogy/writing/video-use/helpers/render.py` — `apply_loudnorm_two_pass`
- ffmpeg two-pass loudnorm pattern: first pass outputs measured I, TP, LRA, threshold; second pass uses those measured values
- Social media targets: YouTube, Instagram, TikTok, X, LinkedIn all converge on -14 LUFS
- Integration plan: `docs/video-use-integration-plan.md` Phase 2, item 5

## Definition of Ready

- [x] Reference implementation in video-use render.py
- [x] ffmpeg loudnorm two-pass pattern well-documented
- [x] Target values specified (-14 LUFS, -1 dBTP, LRA 11)
- [x] A coding agent could begin execution without additional planning context

## Notes

Two-pass is necessary because single-pass loudnorm is an approximation that can be off by several dB. The first pass measures the actual loudness characteristics, and the second pass uses those measurements for precise normalization. Preview mode trades precision for speed.
