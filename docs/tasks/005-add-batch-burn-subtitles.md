---
title: Add batch subtitle burning wrapper
milestone: M2
priority: 3
estimate: 1
blockedBy: [004]
blocks: []
parent: null
---

## Summary

Add a `media-batch-burn-subtitles` command following the existing manifest pattern, enabling batch processing of subtitle burning across multiple files.

## Scope

### In scope

- New module `src/media_tooling/batch_burn_subtitles.py`
- Follow existing batch pattern from `batch_subtitle.py` / `batch_contact_sheet.py`
- Load manifest, iterate items, call `burn_subtitles` for each
- Support `--skip-existing` for resumable batches
- CLI entry point `media-batch-burn-subtitles`
- `pyproject.toml` entry point registration

### Out of scope

- Changes to burn_subtitles.py core logic
- Parallel processing (sequential, consistent with existing batch pattern)

## Deliverables

- `src/media_tooling/batch_burn_subtitles.py`
- Updated `pyproject.toml` with `media-batch-burn-subtitles` entry point

## Acceptance Criteria

- [ ] `media-batch-burn-subtitles manifest.txt` processes all items sequentially
- [ ] `--skip-existing` skips output files that already exist
- [ ] Summary report on completion (successes, failures)
- [ ] Exit code 0 on all success, 1 on any failure
- [ ] Follows exact pattern of existing `batch_subtitle.py` and `batch_contact_sheet.py`
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
```

## Context

- Existing batch pattern: `src/media_tooling/batch_subtitle.py`, `src/media_tooling/batch_contact_sheet.py`
- Shared utilities: `src/media_tooling/batch_utils.py` (`load_manifest_inputs`, `finish_batch`)
- Integration plan: `docs/video-use-integration-plan.md` — Batch support section

## Definition of Ready

- [x] Depends on task 004 (burn_subtitles.py) being complete
- [x] Existing batch pattern is well-established and can be followed directly
- [x] A coding agent could begin execution without additional planning context
