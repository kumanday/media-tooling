# Workflows

This guide shows how to use the toolkit once you already have raw media for a project.

The examples fit agent harnesses that can inspect local files, run commands, and write project artifacts.

Subtitle commands accept `--backend auto|mlx|faster-whisper`. In normal use, `auto` is the right choice.

For MLX transcription, the subtitle commands also run a post-transcription timestamp sanity check. They probe the media duration and compare it to the raw transcript end time. If the duration is near the observed `10x` MLX compression pattern, the toolkit auto-corrects the timestamps and records the correction details in the JSON metadata. Use `--disable-timestamp-correction` if you explicitly want the raw backend timestamps.

## Core workflow

1. Gather the source corpus.
2. Split spoken media from silent media and still images.
3. Generate transcripts and subtitles for spoken media.
4. Generate contact sheets for silent media.
5. Build inventories, analysis notes, storyboards, rough-cut specs, and rough-cut assemblies.

## Media types

### Spoken media

Use the subtitle pipeline for:

- podcasts
- interviews
- narrated tutorials
- course lessons
- product walkthroughs with voice

Typical outputs:

- `assets/audio/`
- `transcripts/`
- `subtitles/`

### Silent or visual-first media

Use the contact-sheet pipeline for:

- screen recordings
- silent demos
- product flows without narration

Typical outputs:

- `assets/reference/`
- `inventory/`
- `analysis/`

### Still images

Inventory these directly and use them in:

- articles
- thumbnails
- chapter cards
- storyboards

## Prompt patterns for an agent harness

Prompts work best when they include:

- where the source files are
- what kind of media you have
- what artifacts you want back
- where outputs should be written
- any constraints such as sequential processing

Ask for outcomes and deliverables. The skills should handle the lower-level steps unless you are debugging or doing something unusual.

In practice, short prompts usually work better than long procedural ones.

## Example 1. Ingest a mixed corpus

```text
I have a new media project in $PROJECT_DIR.

Source folders:
- spoken videos: /path/to/spoken
- silent screen recordings: /path/to/silent
- screenshots: /path/to/images

Please process this source material and leave me with:
- transcripts and subtitles for the spoken material
- contact sheets for the silent recordings
- an inventory of the source material
- short analysis notes I can use for planning
```

## Example 2. Process a podcast episode

```text
I have a podcast episode with:
- one long spoken recording
- one clean audio export
- three short promo clips

Please process the episode and give me:
- transcripts and subtitles
- a shortlist of strong moments for the full episode
- candidate clips for shorts
- quote-worthy sections for graphics or social posts
```

## Example 3. Process tutorial material

```text
I have tutorial materials that include:
- narrated lesson recordings
- silent screen captures of product flows
- screenshots for reference

Please process the materials and give me:
- transcripts and subtitles for the narrated lessons
- contact sheets for the silent recordings
- a suggested storyboard for the main tutorial
- a shortlist of clips for short-form promos
- notes that would help with a companion article
```

## Example 4. Build a shot list after ingestion

```text
The corpus has already been processed in $PROJECT_DIR.

Please review what is already there and give me:
- a shortlist of the strongest clips
- a shot list with timestamps, durations, and purpose
- a note on what still needs to be recorded
```

## Example 5. Prepare a rough cut

```text
Please use the processed artifacts in $PROJECT_DIR to prepare a first-pass rough cut plan.

Please include:
- a proposed sequence
- which clips should carry narration
- which silent clips should be used as B-roll
- where screenshots are enough
- which sections feel weak or need new A-roll
```

## Example 6. Assemble a rough cut from an approved spec

```text
The storyboard and clip choices in $PROJECT_DIR are already approved.

Please turn that approved sequence into a first-pass rough cut, including readable placeholder cards for anything that still needs to be recorded.
```

## Example 7. Prepare final subtitles

```text
The final edit is done.

Please help me prepare this for upload:
- review the existing subtitles
- identify which ones need manual correction
- produce a final checklist for title, description links, chapter timestamps, and subtitle review
```

## Command examples

These commands are the building blocks that the prompt patterns usually trigger. They assume you installed `media-tooling` with `uv tool install` and are running from the project workspace.

### Single spoken file

```bash
media-subtitle \
  "/path/to/video.mp4" \
  --backend auto \
  --model small \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --output-dir "$PROJECT_DIR/transcripts"
```

### Batch spoken media

```bash
media-batch-subtitle \
  --inputs-file "$PROJECT_DIR/inventory/spoken-sources.txt" \
  --audio-dir "$PROJECT_DIR/assets/audio" \
  --transcripts-dir "$PROJECT_DIR/transcripts" \
  --subtitles-dir "$PROJECT_DIR/subtitles" \
  --backend auto \
  --model small \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --skip-existing
```

## Timestamp sanity check

If you are debugging subtitle timing, inspect the JSON metadata:

- `audio_duration`
- `timestamp_correction.raw_last_segment_end`
- `timestamp_correction.ratio_to_media_duration`
- `timestamp_correction.applied`
- `timestamp_correction.scale_factor`

When the sanity check applies a correction, the `.txt`, `.srt`, and `.json` outputs are already written with the corrected timestamps.

### Single silent file

```bash
media-contact-sheet \
  "/path/to/silent-video.mov" \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --ffprobe-bin "$(command -v ffprobe)"
```

### Batch silent media

```bash
media-batch-contact-sheet \
  --inputs-file "$PROJECT_DIR/inventory/silent-sources.txt" \
  --output-dir "$PROJECT_DIR/assets/reference" \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --ffprobe-bin "$(command -v ffprobe)" \
  --skip-existing
```

### Rough cut from a JSON spec

```bash
media-rough-cut \
  --spec "$PROJECT_DIR/rough-cuts/specs/episode-v1.json"
```
