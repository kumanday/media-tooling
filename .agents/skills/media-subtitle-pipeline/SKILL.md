---
name: media-subtitle-pipeline
description: Use when work involves generating transcripts, SRT subtitles, extracted audio, or transcript metadata from local audio or video files. This skill covers the reusable media-tooling commands for single-file and batch spoken-media processing and fits podcasts, interviews, tutorials, courses, narrated demos, and other spoken recordings.
---

# Media Subtitle Pipeline

Use this skill when the task is about spoken media.

Project workspace:

- `$PROJECT_DIR` (the current media project directory)

Primary commands:

- `media-subtitle`
- `media-batch-subtitle`
- `media-translate-subtitles`

Shell helpers expected after setup:

- `extract`
- `subtitle`

## Workflow

1. Confirm that the source is spoken media.
2. Run the installed commands from `$PROJECT_DIR`.
3. Keep project outputs in the project directory.
4. For one file, prefer `media-subtitle`.
5. For many files, create a manifest and use `media-batch-subtitle`.
6. Prefer sequential processing for larger corpora.
7. Use `--skip-existing` when resuming an interrupted batch.

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
media-subtitle \
  "/absolute/path/to/video.mp4" \
  --model small \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --output-dir "$PROJECT_DIR/transcripts"
```

## Batch example

```bash
media-batch-subtitle \
  --inputs-file "$PROJECT_DIR/inventory/spoken-sources.txt" \
  --audio-dir "$PROJECT_DIR/assets/audio" \
  --transcripts-dir "$PROJECT_DIR/transcripts" \
  --subtitles-dir "$PROJECT_DIR/subtitles" \
  --model small \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --skip-existing
```

## Subtitle translation workflow

Do not translate subtitle cues one-by-one from an English `.srt`. That inherits English syntax and breakpoints into the target language.

Instead:

1. Use `media-translate-subtitles --template-out ...` to generate larger translation windows.
2. Translate each window semantically in the target language.
3. Use `media-translate-subtitles --translations-in ... --srt-out ...` to render target-language subtitle cues within the original timing windows.

## Guardrails

- Silent media belongs in the contact-sheet workflow.
- Transcript output should stay searchable and project-local.
- Subtitle translation should happen window-by-window, not source-cue-by-source-cue.
- For large projects, summarize findings instead of dumping raw transcripts into the main conversation.
