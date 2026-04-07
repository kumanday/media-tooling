---
name: media-subtitle-pipeline
description: Use when work involves generating transcripts, SRT subtitles, extracted audio, or transcript metadata from local audio or video files. This skill covers the reusable media-tooling commands for single-file and batch spoken-media processing and fits podcasts, interviews, tutorials, courses, narrated demos, and other spoken recordings.
---

# Media Subtitle Pipeline

Use this skill when the task is about spoken media.

Toolkit root:

- `$TOOLKIT_DIR`

Primary commands:

- `media-subtitle`
- `media-batch-subtitle`

Shell helpers expected after setup:

- `extract`
- `subtitle`

## Workflow

1. Confirm that the source is spoken media.
2. Keep project outputs outside the toolkit directory.
3. For one file, prefer `media-subtitle`.
4. For many files, create a manifest and use `media-batch-subtitle`.
5. Prefer sequential processing for larger corpora.
6. Use `--skip-existing` when resuming an interrupted batch.

## Default output pattern

Put project artifacts in folders such as:

- `assets/audio/`
- `transcripts/`
- `subtitles/`

Do not write project artifacts into the toolkit repository.

## Recommended defaults

- model: `small`
- language: `en`
- ffmpeg path: `$(command -v ffmpeg)`

## Single-file example

```bash
cd "$TOOLKIT_DIR"
uv run media-subtitle \
  "/absolute/path/to/video.mp4" \
  --model small \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --output-dir "$PROJECT_DIR/transcripts"
```

## Batch example

```bash
cd "$TOOLKIT_DIR"
uv run media-batch-subtitle \
  --inputs-file "$PROJECT_DIR/inventory/spoken-sources.txt" \
  --audio-dir "$PROJECT_DIR/assets/audio" \
  --transcripts-dir "$PROJECT_DIR/transcripts" \
  --subtitles-dir "$PROJECT_DIR/subtitles" \
  --model small \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --skip-existing
```

## Guardrails

- Silent media belongs in the contact-sheet workflow.
- Transcript output should stay searchable and project-local.
- For large projects, summarize findings instead of dumping raw transcripts into the main conversation.
