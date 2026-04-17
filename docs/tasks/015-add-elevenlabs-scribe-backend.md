---
title: Add ElevenLabs Scribe as transcription backend
milestone: M4
priority: 3
estimate: 5
blockedBy: []
blocks: [016]
parent: null
---

## Summary

Add `--backend elevenlabs` to `media-subtitle` that uses ElevenLabs Scribe API for word-level timestamps, speaker diarization, and audio event tagging. Keep Whisper as the default (free, local). Make ElevenLabs opt-in via `ELEVENLABS_API_KEY` env var.

## Scope

### In scope

- Modify `src/media_tooling/subtitle.py` to add ElevenLabs backend dispatch
- `--backend whisper` (default): existing behavior
- `--backend elevenlabs`: call ElevenLabs Scribe API
  - Word-level timestamps
  - Speaker diarization (`speaker_id`)
  - Audio event tagging (`(laughter)`, `(applause)`, `(sigh)`)
  - Always verbatim mode
- Cache per-source: never re-transcribe unless source file changed (Hard Rule 9)
- Audio extraction: mono 16kHz PCM WAV before upload
- `requests` as optional dependency (only when ElevenLabs backend selected)
- `ELEVENLABS_API_KEY` env var required for ElevenLabs backend
- Unit tests for backend dispatch and response parsing

### Out of scope

- Batch wrapper update (task 016)
- Changes to packed transcript format (already handles word-level data)
- Other cloud transcription services

## Deliverables

- Modified `src/media_tooling/subtitle.py`
- Tests for ElevenLabs backend
- Updated `pyproject.toml` with `[project.optional-dependencies] elevenlabs = ["requests>=2.31"]`

## Acceptance Criteria

- [ ] `media-subtitle source.mp4 --backend whisper` works identically to current behavior
- [ ] `media-subtitle source.mp4 --backend elevenlabs` calls Scribe API
- [ ] ElevenLabs backend produces word-level timestamps, speaker diarization, audio events
- [ ] Output JSON metadata includes `speaker_id` and `audio_events` fields for ElevenLabs backend
- [ ] Caches per-source: skips re-transcription if source unchanged (Hard Rule 9)
- [ ] `ELEVENLABS_API_KEY` env var required; clear error if missing
- [ ] `requests` is optional dependency, not required for default Whisper backend
- [ ] Unit tests cover: backend dispatch, ElevenLabs response parsing, caching, error handling
- [ ] `scripts/check.sh` passes

## Test Plan

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev ruff check .
uv run --group dev mypy src tests
```

## Context

- Current subtitle.py: `src/media_tooling/subtitle.py` — handles MLX and faster-whisper backends
- Reference: `/Users/magos/dev/trilogy/writing/video-use/helpers/transcribe.py`
- ElevenLabs Scribe API: `https://api.elevenlabs.io/v1/speech-to-text`
- Model: `scribe_v1`, verbatim mode + diarize + audio events + word-level timestamps
- Integration plan: `docs/video-use-integration-plan.md` Phase 4, item 9

## Definition of Ready

- [x] Current subtitle.py backend dispatch pattern can be followed
- [x] Reference implementation in video-use transcribe.py
- [x] API endpoint and parameters specified
- [x] A coding agent could begin execution without additional planning context

## Notes

ElevenLabs Scribe is explicitly recommended over Whisper SRT output in video-use's anti-patterns (item 3: "Whisper SRT output loses sub-second gap data"). The word-level verbatim mode preserves all temporal information needed for precise editing.
