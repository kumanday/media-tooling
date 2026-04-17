---
title: Add batch subtitle support for ElevenLabs backend
milestone: M4
priority: 4
estimate: 1
blockedBy: [015]
blocks: []
parent: null
---

## Summary

Update `media-batch-subtitle` to pass `--backend` flag through to `media-subtitle`, enabling batch transcription with ElevenLabs Scribe alongside the existing Whisper backend.

## Scope

### In scope

- Modify `src/media_tooling/batch_subtitle.py` to accept and pass `--backend` flag
- Add `--api-key` flag or env var passthrough for ElevenLabs

### Out of scope

- Parallel batch processing (video-use uses 4 workers; current pattern is sequential)
- Changes to subtitle.py core logic

## Deliverables

- Modified `src/media_tooling/batch_subtitle.py`

## Acceptance Criteria

- [ ] `media-batch-subtitle manifest.txt --backend elevenlabs` processes all items with Scribe API
- [ ] `--backend whisper` (default) works identically to current behavior
- [ ] API key passthrough works via env var or flag
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
```

## Context

- Current batch: `src/media_tooling/batch_subtitle.py`
- Depends on: task 015 (ElevenLabs backend in subtitle.py)

## Definition of Ready

- [ ] Depends on task 015 being complete
- [x] Existing batch pattern is simple and can be followed
- [x] A coding agent could begin execution once dependency is complete
