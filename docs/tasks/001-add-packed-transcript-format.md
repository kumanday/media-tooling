---
title: Add packed transcript format
milestone: M1
priority: 1
estimate: 3
blockedBy: []
blocks: [003, 009, 010]
parent: null
---

## Summary

Add a `media-pack-transcript` command that converts verbose `.json` transcript metadata into compact phrase-level `takes_packed.md` format, reducing ~100KB JSON to ~12KB LLM-consumable markdown.

## Scope

### In scope

- New module `src/media_tooling/pack_transcript.py` with core logic
- Group words into phrases on silence ≥0.5s or speaker change
- `[start-end]` time prefix per phrase line
- Output as markdown file alongside source transcript
- CLI entry point `media-pack-transcript`
- `pyproject.toml` entry point registration
- Unit tests in `tests/test_pack_transcript.py`

### Out of scope

- Batch wrapper (separate task if needed)
- Integration with subtitle pipeline skill (task 003)
- Changes to existing subtitle.py output format

## Deliverables

- `src/media_tooling/pack_transcript.py`
- `tests/test_pack_transcript.py`
- Updated `pyproject.toml` with `media-pack-transcript` entry point

## Acceptance Criteria

- [ ] `media-pack-transcript transcript.json -o takes_packed.md` produces phrase-level markdown
- [ ] Phrases group on silence gaps ≥0.5s and on speaker changes
- [ ] Each phrase line prefixed with `[start-end]` timestamps (seconds, 3 decimal places)
- [ ] Output is ~12KB for a 1-hour transcript (order of magnitude check)
- [ ] Handles both MLX and faster-whisper JSON formats (dict and object-based segments)
- [ ] Unit tests cover: phrase grouping, silence detection, speaker change, empty input, single-word phrases
- [ ] `scripts/check.sh` passes (unittest + ruff + mypy)

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Read `src/media_tooling/subtitle.py` to understand the JSON metadata format produced by `media-subtitle`
- Reference implementation: `/Users/magos/dev/trilogy/writing/video-use/helpers/pack_transcripts.py`
- The JSON metadata contains word-level timestamps in the `words` array with `start`, `end`, `word` fields
- Integration plan: `docs/video-use-integration-plan.md` Phase 1, item 1

## Definition of Ready

- [x] JSON metadata format documented in existing subtitle.py
- [x] Reference implementation available at video-use/helpers/pack_transcripts.py
- [x] Phrase grouping rules specified (silence ≥0.5s, speaker change)
- [x] A coding agent could begin execution without additional planning context

## Notes

The packed transcript is the single highest-value addition in this integration plan. It transforms raw transcripts into a format that enables dramatically more effective LLM reasoning about video content. Without it, agents must parse ~100KB JSON; with it, they consume ~12KB markdown with full temporal coverage.
