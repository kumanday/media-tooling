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
- `media-pack-transcript`
- `media-timeline-view`

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
8. After transcription, pack the transcript with `media-pack-transcript` before reasoning over it.

### Core pipeline: transcribe → pack → inspect (on demand)

After transcription, always pack the transcript before reasoning over it:

1. **Transcribe** — run `media-subtitle` (or `media-batch-subtitle`) to produce a `.json` transcript metadata file.
2. **Pack** — run `media-pack-transcript` on the `.json` to produce a compact phrase-level `takes_packed.md` file.
3. **Inspect** (on demand) — run `media-timeline-view` only when you need visual context for an editing decision.

The packed transcript (`takes_packed.md`) is the **primary format for agent reasoning**. Use it as the default input for any downstream analysis, summarization, or editing decisions. It is compact, timestamp-addressable, and LLM-consumable.

The timeline view is **not** a default output. Call it only at editing decision points where visual context (filmstrip frames, waveform, silence gaps) would change the agent's choice — for example, when deciding where to cut, checking pacing around a pause, or verifying speaker transitions.

## Worker/subagent use

If the harness supports workers, use them for large batches only when the work
can be partitioned by source file or manifest shard. Each worker should run the
same project-local commands, write artifacts under `$PROJECT_DIR`, and return a
compact handoff:

- source files processed
- transcript/SRT/packed transcript paths created or reused
- failures, retries, and sources skipped by `--skip-existing`
- a short list of notable timestamp ranges or quality issues

Run transcription, packing, and translation worker tasks sequentially. The goal
is to keep raw transcript and translation scratch context out of the main
thread, not to increase concurrent media processing.

Keep raw transcript text and translation scratch work out of the main thread
unless a downstream editing decision needs it. The main thread should reason
from packed transcript paths, summaries, and targeted timestamp excerpts.

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

## Packed transcript

After transcription, pack the verbose JSON transcript into a compact phrase-level markdown file. This is the recommended format for agent reasoning — it groups words into phrases on silence gaps (≥ 0.5 s by default) or speaker changes, and prefixes each line with `[start-end]` timestamps for precise addressing.

### Pack a single transcript

```bash
media-pack-transcript \
  "$PROJECT_DIR/transcripts/video.json" \
  -o "$PROJECT_DIR/transcripts/takes_packed.md"
```

When `--output` is omitted, the output defaults to `takes_packed.md` beside the input file.

### Adjust silence sensitivity

```bash
media-pack-transcript \
  "$PROJECT_DIR/transcripts/video.json" \
  --silence-threshold 0.8 \
  -o "$PROJECT_DIR/transcripts/takes_packed.md"
```

Use a higher threshold (e.g. 0.8) to produce fewer, longer phrases. Use a lower threshold (e.g. 0.3) to split more aggressively on shorter pauses.

### Pack after batch transcription

```bash
# After media-batch-subtitle completes, pack each transcript JSON:
for json_file in "$PROJECT_DIR/transcripts"/*.json; do
  media-pack-transcript "$json_file"
done
```

### Packed transcript output format

Each line in `takes_packed.md` follows this pattern (timestamps in seconds, 3 decimal places):

```
[12.345-15.678] phrase text
```

When speaker diarization is available, a speaker tag is appended:

```
[start-end] S1 phrase text from speaker 1
[start-end] S2 phrase text from speaker 2
```

Use the `[start-end]` ranges to address cuts in the EDL or to locate segments for the timeline view.

## Timeline view

Generate a filmstrip + waveform composite PNG for a time range within a video or audio file. Use this **only at editing decision points** where visual context would change your choice — not as a default step in the pipeline.

Typical decision points where the timeline view helps:

- Deciding where to place a cut or trim.
- Checking pacing around a silence gap.
- Verifying speaker transitions or overlap.
- Confirming that a segment looks and sounds as expected before including it.

### Basic usage

```bash
media-timeline-view \
  "/absolute/path/to/video.mp4" \
  -o "$PROJECT_DIR/transcripts/video-timeline.png"
```

This renders the full duration with 10 evenly-spaced filmstrip frames.

### Inspect a specific time range

```bash
media-timeline-view \
  "/absolute/path/to/video.mp4" \
  --start 30.0 \
  --end 120.0 \
  -o "$PROJECT_DIR/transcripts/video-30s-120s-timeline.png"
```

### With transcript labels and silence shading

```bash
media-timeline-view \
  "/absolute/path/to/video.mp4" \
  --start 30.0 \
  --end 120.0 \
  --transcript "$PROJECT_DIR/transcripts/video.json" \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --ffprobe-bin "$(command -v ffprobe)" \
  -o "$PROJECT_DIR/transcripts/video-30s-120s-timeline.png"
```

When a transcript JSON is supplied, the timeline adds word labels above the waveform and shades silence gaps (≥ 400 ms) for quick visual scanning.

### Skip or overwrite existing output

```bash
# Skip if the PNG already exists (useful in batch loops)
media-timeline-view "/path/to/video.mp4" -o "$PROJECT_DIR/transcripts/video-timeline.png" --skip-existing

# Overwrite an existing PNG
media-timeline-view "/path/to/video.mp4" -o "$PROJECT_DIR/transcripts/video-timeline.png" --overwrite
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
- Always pack transcripts before reasoning over them; use the raw JSON only when word-level timing is needed.
- Use the timeline view only at editing decision points, not as a default pipeline step.
