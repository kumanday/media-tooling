---
title: Add self-evaluation (verify) command
milestone: M3
priority: 2
estimate: 5
blockedBy: [002, 009]
blocks: [014]
parent: null
---

## Summary

Add a `media-verify` command that inspects rendered video output at every cut boundary, checking for visual discontinuity, audio pops, hidden subtitles, overlay misalignment, and duration correctness — catching production errors before showing output to the user.

## Scope

### In scope

- New module `src/media_tooling/verify.py` with core logic
- Run timeline_view on rendered output at every cut boundary (±1.5s window)
- Check for: visual discontinuity/flash/jump, waveform spike (audio pop), subtitle hidden behind overlay, overlay misalignment
- Sample: first 2s, last 2s, 2-3 mid-points for grade consistency, subtitle readability, overall coherence
- Verify output duration matches EDL expectation via ffprobe
- Report findings as structured output (pass/fail per check with details)
- Max 3 self-eval passes — then flag remaining issues to user
- CLI entry point `media-verify`
- `pyproject.toml` entry point registration
- Unit tests in `tests/test_verify.py`

### Out of scope

- Automatic re-render on failure (agent decides whether to re-render)
- Visual diff comparison between segments
- Machine-learning-based quality assessment

## Deliverables

- `src/media_tooling/verify.py`
- `tests/test_verify.py`
- Updated `pyproject.toml` with `media-verify` entry point

## Acceptance Criteria

- [ ] `media-verify final.mp4 --edl edl.json` runs verification checks
- [ ] Generates timeline_view PNGs at every cut boundary (±1.5s)
- [ ] Checks for visual discontinuity/flash/jump at cuts
- [ ] Checks for waveform spikes indicating audio pops
- [ ] Verifies output duration matches EDL `total_duration_s` via ffprobe
- [ ] Samples first 2s, last 2s, 2-3 mid-points for grade consistency
- [ ] Reports structured findings: pass/fail per check with details
- [ ] `--max-passes 3` limits re-evaluation attempts (default 3)
- [ ] Unit tests cover: duration verification, cut boundary extraction, finding report format
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Depends on: timeline_view.py (task 002), edl_render.py (task 009) for EDL format
- Reference: video-use SKILL.md self-evaluation section
- Reference: `/Users/magos/dev/trilogy/writing/video-use/helpers/timeline_view.py`
- Integration plan: `docs/video-use-integration-plan.md` Phase 3, item 7

## Definition of Ready

- [ ] Depends on task 002 (timeline_view) and task 009 (EDL renderer)
- [x] Self-eval process documented in video-use SKILL.md
- [x] Checks clearly specified (visual, audio, subtitle, overlay, duration)
- [x] A coding agent could begin execution once dependencies are complete

## Notes

Self-evaluation is what separates a reliable production pipeline from a "render and hope" workflow. The system inspects its own output before presenting it, catching the most common silent failures automatically.
